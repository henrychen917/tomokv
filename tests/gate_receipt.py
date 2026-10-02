#!/usr/bin/env python3
"""Full gate receipts and independent local standing-null promotion.

Promotion retains null evidence; only a trusted comparison plus complete
correctness execution can certify a push/release source tree and binary.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

from abba_evidence import (validate_measurements, validate_null, validate_comparison, match_null, null_result,
                           instrument, validate_campaign_evidence, validate_null_integrity, validate_holdout,
                           null_resolution, resolution_summary, resolution_text, NULL_MAX_AGE, utc_seconds)
from abba_instrument import instrument_fingerprint, validate_fingerprint
from abba_saturation import saturation_exempt


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
ABBA_LABEL = "ABBA comparison + saturation negative controls"
# These are retirement guards, not inventories. All rows/cells in the CURRENT files are required,
# including future additions. The structural checks below also preserve the 64 original cells,
# restored 96 multi-key cells, and the 18 deliberate supplemental regimes.
ORDER = ["A", "B", "B", "A"]
HARNESS_DIRS = ("tests/", ".githooks/", "bench/", "benchmarks/", "scripts/", "make/")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, label, *, positive=False):
    require(type(value) in (int, float) and math.isfinite(value) and
            (value > 0 if positive else value >= 0), f"invalid {label}")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args, data=None):
    result = subprocess.run(["git", "-C", str(root), *args], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    require(result.returncode == 0, result.stderr.decode(errors="replace").strip())
    return result.stdout


def object_file(path):
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode):
        content, mode = os.fsencode(os.readlink(path)), "120000"
    else:
        require(stat.S_ISREG(before.st_mode), f"unsupported source file type: {path}")
        content = path.read_bytes()
        mode = "100755" if before.st_mode & 0o111 else "100644"
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after), f"file changed while fingerprinting: {path}")
    return mode, digest(content)


def fingerprint_entries(entries):
    entries = sorted(entries, key=lambda item: os.fsencode(item["path"]))
    return {"sha256": digest(canonical(entries)), "entries": entries}


def source_fingerprint(root):
    # Git's index supplies tracked names even when ignored. Nonignored untracked sources count
    # too, and staging/committing those same bytes later changes neither this manifest nor its hash.
    # Raw file bytes and executable/symlink modes match Git trees; no HEAD/mtime/index hash is used.
    names = set(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"))
    entries = []
    for raw in names - {b""}:
        name = os.fsdecode(raw)
        path = root / name
        require(not path.parent.is_symlink(), f"symlinked source parent: {name}")
        try:
            mode, checksum = object_file(path)
        except FileNotFoundError:
            continue  # A tracked deletion has the same fingerprint before and after committing it.
        entries.append({"path": name, "mode": mode, "sha256": checksum})
    return fingerprint_entries(entries)


def harness_from_source(source):
    # Keep the full release-test/driver binding, even for helpers outside the ABBA
    # instrument. Standing null reuse now has its own transitive measurement scope.
    return fingerprint_entries([row for row in source["entries"] if
        row["path"] == "Makefile" or row["path"].startswith(HARNESS_DIRS)])


def harness_fingerprint(root):
    return harness_from_source(source_fingerprint(root))


def tree_fingerprint(root, revision):
    rows = git(root, "ls-tree", "-r", "-z", revision + "^{tree}").split(b"\0")
    items = []
    for row in rows:
        if not row:
            continue
        header, rawpath = row.split(b"\t", 1)
        mode, kind, oid = header.split()
        require(kind == b"blob" and mode in (b"100644", b"100755", b"120000"),
                "submodules/unsupported Git modes cannot receive a source receipt")
        items.append((os.fsdecode(rawpath), mode.decode(), oid))
    payload = git(root, "cat-file", "--batch", data=b"".join(oid + b"\n" for _, _, oid in items))
    offset, entries = 0, []
    for name, mode, oid in items:
        end = payload.index(b"\n", offset)
        got, kind, size = payload[offset:end].split()
        require(got == oid and kind == b"blob", "Git returned another object")
        offset = end + 1
        length = int(size)
        content = payload[offset:offset + length]
        require(len(content) == length and payload[offset + length:offset + length + 1] == b"\n",
                "truncated Git object")
        offset += length + 1
        entries.append({"path": name, "mode": mode, "sha256": digest(content)})
    require(offset == len(payload), "unexpected Git object output")
    return fingerprint_entries(entries)


def read_json(path, *, content=None):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, f"duplicate JSON key {key} in {path}")
            result[key] = value
        return result
    return json.loads(path.read_text() if content is None else content, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid {value}")))


def write_json(path, value, *, exclusive=False):
    write_bytes(path, canonical(value) + b"\n", exclusive=exclusive)


def write_bytes(path, data, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def history_directory(root):
    directory = root / ".gate-history" / "receipts"
    # Never silently hide source: the repository must explicitly ignore local gate evidence.
    # In particular, do not mutate the common repository's info/exclude from another worktree.
    relative = ".gate-history/receipts/probe.json"
    result = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", relative])
    require(result.returncode == 0, ".gate-history/ must be ignored before storing local receipts")
    require(not git(root, "ls-files", "--", ".gate-history").strip(),
            "receipt history must not contain tracked files")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def inventory(root, path):
    # One authoritative parser, including implicit tail geometry and value size.
    from abbagate import read_cells
    from dataclasses import asdict
    from gate_measurements import load as load_measurements
    measurements_path = root / "tests/gate_measurements.json"
    measurements = load_measurements(measurements_path) if measurements_path.is_file() else {"load_floors": {}}
    cells = [asdict(cell) for cell in read_cells(path, measurements=measurements,
             instrument_sha256=instrument_fingerprint(root)["sha256"])]
    require(cells and len({cell["id"] for cell in cells}) == len(cells), "duplicate/empty cell inventory")
    # Requiring the complete cross products catches retirement even if someone replaces removed
    # cells with duplicates at another geometry and preserves the numeric count.
    def axis(c):
        return (c["mode"], c["read_local"], c["overlap"], c["reorder"], c["op"],
                c["depth"], c["conns"], c.get("atomic", 1), c.get("mix", "-"))
    actual = {axis(c) for c in cells}
    required = set()
    for mode, rl, ov, ro in product(("1s", "2s"), (0, 1), (0, 1), (0, 1)):
        for op, depth in product(("GET", "SET"), (1, 32)):
            required.add((mode, rl, ov, ro, op, depth, 512, 1, "-"))
        for op, depth in product(("MGET", "MSET"), (1, 8, 32)):
            required.add((mode, rl, ov, ro, op, depth, 512, 1, "-"))
    for mode in ("1s", "2s"):
        for rl in (0, 1):
            required.add((mode, rl, 1, 1, "MIX", 1, 512, 1, "7:1"))
            required.add((mode, rl, 1, 1, "GET", 32, 2048, 1, "-"))
        required.add((mode, 1, 1, 1, "MIX8", 128, 512, 1, "18:14"))
        for op in ("MGET", "MSET"):
            required.add((mode, 1, 1, 1, op, 8, 512, 0, "-"))
        for ro in (0, 1):
            required.add((mode, 0, 1, ro, "REORDER", 8, 512, 1, "8:2"))
    require(required <= actual, f"full inventory retired {len(required - actual)} required cell geometries")
    for cell in cells:
        require(saturation_exempt(cell) or cell.get("instances", 0) > 0,
                f"{cell['id']}: unmeasured load floor; re-pin with --escalate before certification")
        require(cell["op"] != "REORDER" or cell.get("score") == "p999",
                f"{cell['id']}: reorder needs p99.9 scoring")
    return {"path": str(path.relative_to(root)), "sha256": digest(path.read_bytes()),
            "count": len(cells), "cells": cells}


def ledger_rows(path, *, passing):
    rows = []
    text = path.read_text()
    require(text.endswith("\n"), f"incomplete ledger: {path}")
    for lineno, line in enumerate(text.splitlines(), 1):
        fields = line.split("\t")
        require(len(fields) == 3 and fields[0] in ("ok", "FAIL"), f"invalid ledger row {path}:{lineno}")
        verdict, seconds, label = fields
        duration = number(float(seconds), "row seconds")
        require(label and not any(c in label for c in "\r\n\0"), "invalid ledger label")
        require(not passing or verdict == "ok", f"nonpassing row: {label}")
        rows.append({"verdict": verdict, "seconds": duration, "label": label})
    return rows


def expected_count(root, nic):
    matches = re.findall(r"^EXPECT_FULL=([0-9]+)\b", (root / "tests/gate.sh").read_text(), re.M)
    require(len(matches) == 1 and int(matches[0]) > 0, "full gate count missing or invalid")
    return int(matches[0]) + int(nic)


def current_campaign(root, campaign):
    """Check a frozen post-import plan against today's code, files and machine."""
    from abbagate import WINDOW
    from gateplan import validate_axes
    require(campaign.get("schema") == 1 and campaign.get("kind") == "frozen-null-campaign",
            "missing frozen null campaign")
    require(campaign["instrument"] == instrument_fingerprint(root), "campaign instrument/runtime changed")
    require(campaign["inventory"] == inventory(root, root / "tests/headline_cells.txt"),
            "campaign inventory/imported plans changed")
    require(campaign["measurements_sha256"] == digest((root / "tests/gate_measurements.json").read_bytes()),
            "campaign imported runtime inputs changed")
    for name in ("binary", "generator"):
        artifact = campaign[name]
        require(object_file(Path(artifact["path"])) == ("100755", artifact["sha256"]),
                f"campaign {name} bytes/mode changed")
    env = campaign["environment"]
    require(env["uname"] == list(os.uname()), "campaign machine environment changed")
    # Replay need not run on the measured CPUs, but their topology must still match.
    validate_axes(env["server_physical"], env["server_smt"], env["load_physical"], env["load_smt"],
                  check_available=False)
    require(campaign["window_seconds"] == WINDOW, "campaign measurement window changed")
    if campaign.get("reorder_controls"):
        from abba_reorder_control import validate_binding, needs_proof, refusal_hint
        from abbagate import Cell
        cells = [Cell(**cell) for cell in campaign["inventory"]["cells"]]
        try:
            validate_binding(campaign["reorder_controls"], cells=cells,
                fingerprint=campaign["instrument"], binary_sha256=campaign["binary"]["sha256"],
                environment=env, before=campaign["frozen_at"])
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
            raise ValueError(f"frozen read-local receipt invalid: {error}" + refusal_hint(
                ','.join(cell.id for cell in cells if needs_proof(cell)),
                dict(candidate=campaign['binary'], environment=env,
                     cell_source=dict(path=str(root / campaign['inventory']['path']))))) from error
    return campaign


def freeze_null(root, args):
    """Freeze runtime inputs AFTER replay/import, with no server or generator boot."""
    from gate_measurements import (validate_fast_calibration, shape, load as load_measurements,
                                   apply_floor, geometry, import_calibration)
    from abbagate import Cell
    import copy
    from abbagate import WINDOW
    from abba_null_sampling import policy
    calibration = read_json(args.calibration)
    from abba_reorder_control import identity, validate_report
    binding = identity(args.reorder_controls) if getattr(args, "reorder_controls", None) else None
    validate_report(calibration, binding, before=utc_seconds(calibration["started_utc"]))
    fingerprint = instrument_fingerprint(root)
    validate_fast_calibration(calibration, fingerprint)
    require(calibration.get("subset") == "full" and not calibration.get("only"),
            "freeze requires a completed full calibration")
    inv = inventory(root, root / "tests/headline_cells.txt")
    require(calibration["cell_source"]["sha256"] == inv["sha256"] and
            calibration["cell_source"]["total_cells"] == inv["count"] and
            [row["cell"]["id"] for row in calibration["cells"]] == [cell["id"] for cell in inv["cells"]] and
            all(shape(row["cell"]) == shape(cell) for row, cell in zip(calibration["cells"], inv["cells"])),
            "freeze calibration differs from current full inventory")
    measurements = load_measurements(root / "tests/gate_measurements.json")
    replayed = copy.deepcopy(measurements)
    import_calibration(args.calibration, replayed, [Cell(**cell) for cell in inv["cells"]])
    require(replayed == measurements, "freeze requires replay/import of this complete calibration first")
    for cell in inv["cells"]:
        if not saturation_exempt(cell):
            applied = apply_floor(cell, measurements, geometry(calibration["environment"]), fingerprint["sha256"])
            require(applied["instances"] == cell["instances"] > 0 and
                    applied.get("ceiling_status", "") == cell.get("ceiling_status", ""),
                    f"{cell['id']}: imported floor does not match frozen geometry")
    inputs_sha = digest((root / "tests/gate_measurements.json").read_bytes())
    env = {**calibration["environment"], "population_by_arm": {"A": "wire", "B": "wire"},
           "measurements_sha256": inputs_sha}
    campaign = dict(schema=1, kind="frozen-null-campaign", frozen_at=time.time(),
        instrument=fingerprint, inventory=inv, environment=env, measurements_sha256=inputs_sha,
        window_seconds=WINDOW, calibration_sha256=digest(args.calibration.read_bytes()),
        binary={key: calibration["candidate"][key] for key in ("path", "sha256")},
        ceiling_loads=measurements.get("ceiling_loads", {}),
        generator=dict(path=env["memtier_path"], sha256=env["memtier_sha256"]),
        metric_scope="rate/latency/p999 only; cycles/op UNPROVEN", null_sampling_policy=policy())
    if binding:
        campaign["reorder_controls"] = binding
    current_campaign(root, campaign)
    require(args.output.resolve().is_relative_to(root), "campaign output must be inside this worktree")
    write_json(args.output, campaign, exclusive=True)
    return args.output


def validate_campaign(root, campaign, report, *, now):
    current_campaign(root, campaign)
    from abba_reorder_control import validate_report
    from abba_evidence import utc_seconds
    validate_report(report, campaign.get("reorder_controls"), before=utc_seconds(report["started_utc"]))
    started, environment = validate_measurements(report, now=now, expected_source=campaign["inventory"],
        expected_cells=campaign["inventory"]["cells"], expected_instrument=campaign["instrument"])
    require(campaign["frozen_at"] <= started + 1 <= now + 1 and now - started <= NULL_MAX_AGE,
            "campaign must start after freeze and be at most 24 hours old")
    require(instrument(environment) == instrument(campaign["environment"]),
            "campaign environment/geometry/runtime inputs differ")
    require(report["window_seconds"] == campaign["window_seconds"], "campaign window differs")
    require(report.get("ceiling_loads", {}) == campaign.get("ceiling_loads", {}),
            "campaign ceiling-control provenance differs")
    if report.get("run_kind") == "null-control":
        require(report.get("null_sampling_policy") == campaign.get("null_sampling_policy"),
                "campaign null sampling policy differs")
    validate_campaign_evidence(report)


def promote_null(root, args):
    """Publish only standing-null evidence; no previous null or receipt is consulted."""
    source_bytes = args.null_result.read_bytes()
    report, campaign = read_json(args.null_result), read_json(args.campaign)
    now = time.time()
    validate_campaign(root, campaign, report, now=now)
    validate_null(report, now=now)
    validate_null_integrity(report)
    require(report["candidate"]["sha256"] == campaign["binary"]["sha256"],
            "null measured another frozen binary")
    for arm in ("A", "B"):
        require(object_file(args.null_result.parent / f"binary-{arm}") ==
                ("100755", campaign["binary"]["sha256"]), f"null binary-{arm} bytes differ")
    require(args.null_result.read_bytes() == source_bytes, "null source changed during promotion")
    directory = history_directory(root)
    archive = directory / "null-promotions" / digest(source_bytes)
    provenance = dict(kind="standing-null-promotion", promoted_at=now,
        source_path=str(args.null_result.resolve()), source_sha256=digest(source_bytes),
        campaign_sha256=digest(canonical(campaign)), instrument_sha256=campaign["instrument"]["sha256"],
        independent_resolution="PENDING HOLDOUT", cycles_op_resolution="UNPROVEN")
    # The source and plan remain immutable audit artifacts. Only full-null.json
    # is a mutable default. An interrupted replacement leaves its previous bytes intact.
    archive.mkdir(parents=True, exist_ok=True)
    for name, data in (("source.json", source_bytes), ("campaign.json", canonical(campaign) + b"\n")):
        path = archive / name
        if path.exists():
            require(path.read_bytes() == data, "promotion archive differs")
        else:
            write_bytes(path, data, exclusive=True)
    promoted = {**report, "promotion": provenance}
    provenance_path = archive / (digest(canonical(provenance)) + ".promotion.json")
    if not provenance_path.exists():
        write_json(provenance_path, provenance, exclusive=True)
    current_campaign(root, campaign)
    path = directory / "baselines/full-null.json"
    write_json(path, promoted)
    print("Standing null: " + resolution_text(resolution_summary(promoted)))
    return path


def replay_null(path):
    """Read historical raw blocks without granting current provenance or promotion."""
    content = path.read_bytes()
    report = read_json(path, content=content)
    rows = null_resolution(report)
    replay = dict(kind="null-resolution-replay", reporting_only=True, promotable=False,
                  source_sha256=digest(content), resolution=rows)
    replay["summary"] = resolution_summary({**report, "null_control": {"resolution": rows}})
    return replay


def verify_null_holdout(root, args):
    campaign = read_json(args.campaign)
    report, control = read_json(args.comparison), read_json(args.null_result)
    now = time.time()
    validate_campaign(root, campaign, control, now=now)
    validate_campaign(root, campaign, report, now=now)
    result = validate_holdout(report, control, now=now)
    write_json(args.output, result, exclusive=True)
    return args.output


def begin(root, args):
    require(args.tier in ("full", "push", "release"), "smoke/iteration gates cannot create push receipts")
    directory = history_directory(root)
    require(re.fullmatch(r"[A-Za-z0-9_.:-]+", args.run_id) and args.run_id not in (".", ".."), "invalid run ID")
    baseline, baseline_identity, withheld = [], None, None
    nic = args.nic
    try:
        baseline = ledger_rows(args.expected_ledger, passing=False)
        if getattr(args, "nic_auto", False):
            nic = any(row["label"] == "NIC regression cells (all within -3%)" for row in baseline)
        count = expected_count(root, nic)
        require(len(baseline) == count and sum(r["label"] == ABBA_LABEL for r in baseline) == 1,
                f"trusted baseline ledger must contain exactly {count} rows including the ABBA negative-control row")
        baseline_identity = {"path": str(args.expected_ledger.resolve()),
                             "sha256": digest(args.expected_ledger.read_bytes())}
    except (ValueError, OSError) as error:
        if not getattr(args, "allow_missing_baseline", False):
            raise
        # Bootstrap is a state worth preserving, never authorization to shrink/skip the gate or
        # to trust its own newly observed labels. An owner can review the completed full ledger
        # and explicitly supply it as GATE_RECEIPT_BASELINE for the next run. Automatic discovery
        # uses only baselines written after a previous receipt was successfully certified.
        baseline = []
        withheld = "missing/invalid trusted baseline: " + str(error)
        print("GATE RECEIPT PENDING: " + withheld + "; all gate work still runs; no push receipt will be issued", file=sys.stderr)
    count = expected_count(root, nic)
    source = source_fingerprint(root)
    instrument = instrument_fingerprint(root)
    require({row["path"] for row in instrument["entries"]} <= {row["path"] for row in source["entries"]},
            "instrument imports an ignored/untracked dependency absent from the release source manifest")
    state = {"schema": SCHEMA, "kind": "gate-start", "run_id": args.run_id, "tier": args.tier,
             "started_at": time.time(), "source": source, "harness": harness_from_source(source),
             "instrument": instrument,
             "inventory": inventory(root, args.cells.resolve()), "expected_checks": count,
             "expected_labels": [r["label"] for r in baseline], "nic": nic,
             "baseline": baseline_identity, "withheld_reason": withheld}
    path = directory / "runs" / args.run_id / "start.json"
    write_json(path, state, exclusive=True)
    return path


def load_start(root, path):
    require(path.resolve().is_relative_to(history_directory(root).resolve() / "runs"),
            "start manifest must be in this worktree's local receipt history")
    state = read_json(path)
    require(state.get("schema") == SCHEMA and state.get("kind") == "gate-start", "invalid start manifest")
    require(validate_fingerprint(state.get("instrument")) == instrument_fingerprint(root)["sha256"],
            "measurement instrument/runtime changed since gate start")
    require(source_fingerprint(root) == state["source"], "source contents/modes changed since gate start")
    require(inventory(root, root / state["inventory"]["path"]) == state["inventory"], "cell inventory changed")
    require(expected_count(root, state["nic"]) == state["expected_checks"], "gate row count changed")
    require(state.get("withheld_reason") or len(state["expected_labels"]) == state["expected_checks"] and
            state["expected_labels"].count(ABBA_LABEL) == 1, "start has incomplete expected row inventory")
    return state


def bind(root, args):
    state = load_start(root, args.start)
    binary = args.candidate.resolve()
    require(binary.is_relative_to(root), "candidate must be built inside this worktree")
    mode, checksum = object_file(binary)
    require(mode == "100755", "candidate must be an executable regular file")
    binding = {"schema": SCHEMA, "kind": "gate-candidate", "run_id": state["run_id"],
               "bound_at": time.time(), "path": str(binary.relative_to(root)), "sha256": checksum,
               "source_sha256": state["source"]["sha256"], "start_sha256": digest(args.start.read_bytes())}
    path = args.start.parent / "candidate.json"
    write_json(path, binding, exclusive=True)
    return path


def validate_abba(report, state, *, now, candidate=None, null=False):
    # Shared shape/null validation also guards standalone smoke. A push retains this stronger
    # wrapper: every cell in the current full inventory, including future additions, is required.
    require(report.get("subset") == "full" and not report.get("only"),
            "only the full ABBA set can certify a push")
    validate_fingerprint(state.get("instrument"))
    if null:
        validate_null(report, now=now)
    else:
        require(report.get("verdict") == "PASS" and report.get("comparison_trusted") is True and
                report.get("run_kind") == "comparison" and not report.get("only"),
                "only a complete trusted comparison PASS can certify a push")
    return validate_measurements(report, now=now, expected_source=state["inventory"],
        expected_cells=state["inventory"]["cells"], harness=None if null else state["harness"]["sha256"],
        candidate=candidate, expected_instrument=state["instrument"])


def observations(path, state, actual, finished):
    expected = set(state["expected_labels"])
    selected = []
    seen = set()
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if row.get("run_id") != state["run_id"]:
            continue
        require(row.get("schema") == 1 and row.get("timing") == "own-row" and row.get("verdict") == "ok"
                and row.get("timed_out") is False, "row history has a failure, timeout, or non-owned timing")
        require(row.get("observation_id") and row["observation_id"] not in seen, "duplicate/missing row observation ID")
        seen.add(row["observation_id"])
        when = number(row.get("recorded_at"), "row recording time", positive=True)
        require(state["started_at"] <= when <= finished, "row history is from outside this run")
        # These explicit fields come from the row recorder, not a regex stripping brackets from
        # arbitrary labels. Hidden build prerequisites remain audited but do not invent scored
        # gate rows. Every scored observation must correspond to a counted ledger occurrence.
        require(type(row.get("scored")) is bool, "row observation lacks explicit scored flag")
        if row["scored"]:
            require(row.get("ledger_label") in expected, f"unplanned scored observation: {row.get('label')}")
        else:
            require(row.get("ledger_label", "missing") is None, "unscored dependency has a ledger label")
        selected.append(row)
    key = lambda r: (r["verdict"], r["seconds"], r.get("ledger_label", r["label"]))
    require(Counter(map(key, (row for row in selected if row["scored"]))) == Counter(map(key, actual)),
            "actual ledger rows/durations lack matching independent own-row observations")
    return selected


def finish(root, args):
    state = load_start(root, args.start)
    require(state.get("baseline") is not None and not state.get("withheld_reason"),
            (state.get("withheld_reason") or "missing trusted baseline") +
            "; completed full-run evidence is retained, but its rows are not automatically trusted")
    report, control = read_json(args.abba_result), read_json(args.null_result)
    summary = resolution_summary(report, control)
    print("Receipt ABBA: " + resolution_text(summary))
    require(not summary["unresolved_cells"], "receipt withheld: " + resolution_text(summary))
    candidate = read_json(args.start.parent / "candidate.json")
    require(candidate.get("start_sha256") == digest(args.start.read_bytes()) and
            candidate.get("source_sha256") == state["source"]["sha256"], "candidate binding is from another run")
    require(object_file(root / candidate["path"]) == ("100755", candidate["sha256"]), "candidate binary changed after binding")
    completed = read_json(args.gate_result)
    now = time.time()
    # Minimal coordinator artifact, written only AFTER all correctness children and ABBA are reaped:
    # {schema:1, run_id, tier:'push'|'release'|'full', completed:true, verdict:'PASS', exit_code:0,
    #  started_at:<same start.json value>, finished_at:<UNIX>, checks:EXPECT_FULL, passed:EXPECT_FULL, failed:0,
    #  skipped:0, abba_exit_code:0, nic_checked:false, candidate_sha256:<bound binary digest>}.
    # A human label list is an expectation, never proof of execution: receipt issuance also needs
    # the exact final ledger AND the gate_history recorder's independent per-row observations.
    require(completed.get("schema") == 1 and completed.get("run_id") == state["run_id"] and
            completed.get("tier") == state["tier"] and completed.get("completed") is True and
            completed.get("verdict") == "PASS", "gate coordinator did not complete the requested full tier")
    count = state["expected_checks"]
    for key, value in {"exit_code": 0, "checks": count, "passed": count, "failed": 0, "skipped": 0,
                       "abba_exit_code": 0, "nic_checked": state["nic"],
                       "candidate_sha256": candidate["sha256"], "started_at": state["started_at"]}.items():
        require(completed.get(key) == value and type(completed.get(key)) is type(value), f"incorrect gate completion {key}")
    ended = number(completed.get("finished_at"), "gate completion time", positive=True)
    require(state["started_at"] <= candidate["bound_at"] <= ended <= now, "invalid gate/candidate times")
    actual = ledger_rows(args.ledger, passing=True)
    require(Counter(row["label"] for row in actual) == Counter(state["expected_labels"]),
            "gate rows are missing, duplicated, or different from the trusted full baseline")
    observed = observations(args.observations, state, actual, ended)
    started, environment = validate_abba(report, state, now=ended, candidate=candidate)
    require(started + 1 >= candidate["bound_at"], "ABBA predates this candidate binding")
    validate_abba(control, state, now=ended, null=True)
    validate_comparison(report, control, now=ended)
    require(source_fingerprint(root) == state["source"], "source changed while validating gate evidence")
    evidence = {"start": state, "candidate": candidate, "coordinator": completed,
                "ledger": actual, "observations": observed, "abba": report, "null": control}
    # Retain evidence locally so a later run rotating build/ logs cannot turn the hook into either
    # a false acceptance or a false rejection. This is an audit receipt, not a signature against a
    # malicious owner rewriting local files or bypassing Git hooks with --no-verify.
    evidence_path = args.start.parent / "evidence.json"
    write_json(evidence_path, evidence, exclusive=True)
    receipt = {"schema": SCHEMA, "kind": "full-gate-receipt", "verdict": "PASS", "run_id": state["run_id"],
               "source": state["source"], "candidate": candidate, "inventory": state["inventory"],
               "completed_at": ended, "evidence_sha256": digest(evidence_path.read_bytes()),
               "null_control_sha256": control["candidate"]["sha256"], "resolution_summary": summary}
    path = args.start.parent / "receipt.json"
    write_json(path, receipt, exclusive=True)
    # Only an issued receipt advances the trusted correctness ledger. Standing nulls
    # are published separately by explicit promote-null; a receipt cannot overwrite it.
    directory = history_directory(root) / "baselines"
    ledger = "".join(f"{row['verdict']}\t{row['seconds']!r}\t{row['label']}\n" for row in actual)
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".full-ledger-", dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(ledger)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / "full.tsv")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def coordinator(root, args):
    state = read_json(args.start) if args.start is not None else {}
    binding_path = args.start.parent / "candidate.json" if args.start is not None else None
    binding = read_json(binding_path) if binding_path is not None and binding_path.exists() else {}
    successful = args.failed == 0 and args.abba_rc == 0 and args.cleanup_rc == 0
    result = {"schema": 1, "run_id": args.run_id, "tier": args.tier,
              "completed": args.cleanup_rc == 0, "verdict": "PASS" if successful else "FAIL",
              "exit_code": 0 if successful else 1, "started_at": state.get("started_at"),
              "finished_at": time.time(), "checks": args.passed + args.failed, "passed": args.passed,
              "failed": args.failed, "skipped": 0, "abba_exit_code": args.abba_rc,
              "nic_checked": bool(args.nic), "candidate_sha256": binding.get("sha256"),
              "cleanup_exit_code": args.cleanup_rc}
    write_json(args.output, result, exclusive=True)
    return args.output


def validate_receipt(root, path, source):
    receipt = read_json(path)
    require(receipt.get("schema") == 1 and receipt.get("kind") == "full-gate-receipt" and
            receipt.get("verdict") == "PASS" and receipt.get("source") == source, "receipt certifies another source tree")
    evidence_path = path.parent / "evidence.json"
    require(digest(evidence_path.read_bytes()) == receipt.get("evidence_sha256"), "receipt evidence changed or disappeared")
    evidence = read_json(evidence_path)
    require(evidence["start"]["source"] == source and evidence["candidate"] == receipt["candidate"] and
            evidence["start"]["inventory"] == receipt["inventory"], "receipt/evidence identity mismatch")
    require(inventory(root, root / receipt["inventory"]["path"]) == receipt["inventory"], "receipt cell inventory is stale")
    state = evidence["start"]
    count = expected_count(root, state["nic"])
    require(state["expected_checks"] == count and len(state["expected_labels"]) == count and
            state["expected_labels"].count(ABBA_LABEL) == 1, "receipt has an incomplete expected row inventory")
    completed = evidence["coordinator"]
    for key, value in {"schema": 1, "completed": True, "verdict": "PASS", "run_id": state["run_id"],
                       "tier": state["tier"], "checks": count, "passed": count, "failed": 0, "skipped": 0,
                       "exit_code": 0, "abba_exit_code": 0, "nic_checked": state["nic"]}.items():
        require(completed.get(key) == value and type(completed.get(key)) is type(value),
                f"receipt coordinator has invalid {key}")
    require(state["tier"] in ("full", "push", "release"), "smoke receipt cannot certify a push")
    actual, observed = evidence["ledger"], evidence["observations"]
    require(Counter(row["label"] for row in actual) == Counter(state["expected_labels"]) and
            all(row["verdict"] == "ok" for row in actual), "receipt has missing or failed ledger rows")
    require(len({row["observation_id"] for row in observed}) == len(observed) and all(
            row["schema"] == 1 and row["run_id"] == state["run_id"] and row["timing"] == "own-row" and
            row["timed_out"] is False and row["verdict"] == "ok" and
            type(row.get("scored")) is bool and (row.get("ledger_label") in state["expected_labels"]
            if row["scored"] else row.get("ledger_label", "missing") is None) and
            state["started_at"] <= row["recorded_at"] <= completed["finished_at"] for row in observed),
            "receipt observations are missing, failed, duplicated, or from another run")
    require(Counter((row["label"], row["seconds"]) for row in actual) ==
            Counter((row["ledger_label"], row["seconds"]) for row in observed if row["scored"]), "receipt row evidence differs")
    binary = receipt["candidate"]
    require(binary["source_sha256"] == source["sha256"] and binary["sha256"] == completed["candidate_sha256"],
            "receipt candidate/source binding differs")
    require(state["started_at"] <= binary["bound_at"] <= completed["finished_at"] <= time.time(),
            "receipt time ordering differs")
    begin_at, environment = validate_abba(evidence["abba"], state, now=completed["finished_at"], candidate=binary)
    validate_abba(evidence["null"], state, now=completed["finished_at"], null=True)
    validate_comparison(evidence["abba"], evidence["null"], now=completed["finished_at"])
    require(evidence["null"]["candidate"]["sha256"] == receipt["null_control_sha256"], "receipt null arms differ")
    require(begin_at + 1 >= binary["bound_at"], "receipt ABBA predates the candidate binding")
    require(object_file(root / binary["path"]) == ("100755", binary["sha256"]), "receipt candidate binary changed or is missing")
    return receipt


def verify_refs(root, updates):
    live = source_fingerprint(root)
    directory = history_directory(root)
    receipts = list((directory / "runs").glob("*/receipt.json"))
    checked = []
    for local_ref, oid in updates:
        require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid), "invalid local object ID")
        if set(oid) == {"0"}:
            continue  # A deletion publishes no source or binary.
        git(root, "rev-parse", "--verify", oid + "^{commit}")  # Annotated release tags peel to commits.
        source = tree_fingerprint(root, oid)
        require(source == live, f"{local_ref}: pushed Git tree differs from the current validated worktree contents/modes")
        failures, valid = [], None
        for path in receipts:
            try:
                valid = validate_receipt(root, path, source)
                break
            except (ValueError, OSError, KeyError, TypeError) as exc:
                failures.append(str(exc))
        require(valid is not None, f"{local_ref}: no successful full gate receipt for this tree/binary; " +
                ("; ".join(sorted(set(failures))) if failures else "run the full push gate"))
        checked.append((local_ref, valid["run_id"]))
    require(source_fingerprint(root) == live, "source changed during pre-push verification")
    return checked


def install(root, *, uninstall=False):
    enabled = subprocess.run(["git", "-C", str(root), "config", "--bool", "extensions.worktreeConfig"],
                             stdout=subprocess.PIPE, check=False).stdout.strip()
    require(enabled == b"true", "extensions.worktreeConfig is not enabled; changing it would affect the common repository. "
            "Use the reversible per-command wrapper: git -c core.hooksPath=.githooks push")
    directory = history_directory(root)
    saved = directory / "hook-config.json"
    current = subprocess.run(["git", "-C", str(root), "config", "--worktree", "--get", "core.hooksPath"],
                             stdout=subprocess.PIPE, check=False)
    value = current.stdout.decode().rstrip("\n") if current.returncode == 0 else None
    target = str(root / ".githooks")
    if uninstall:
        prior = read_json(saved)
        require(value == prior["installed"], "worktree hook configuration changed since installation")
        if prior["previous"] is None:
            git(root, "config", "--worktree", "--unset-all", "core.hooksPath")
        else:
            git(root, "config", "--worktree", "core.hooksPath", prior["previous"])
        saved.unlink()
    else:
        require(not saved.exists(), "hook installation is already recorded; use --uninstall to restore it")
        require((root / ".githooks/pre-push").is_file(), "pre-push hook missing")
        write_json(saved, {"installed": target, "previous": value}, exclusive=True)
        git(root, "config", "--worktree", "core.hooksPath", target)


def self_test():
    import copy
    import shutil
    import unittest
    from unittest import mock
    from gate_ledger_fixture import validate_fixture, self_test as fixture_controls

    # Fail once, with the source-declared missing/extra labels, before any of the
    # receipt fixtures call begin(). A partial gate ledger cannot redefine this list.
    try:
        labels = validate_fixture(ROOT)
    except (ValueError, OSError, KeyError) as error:
        print(f"RECEIPT FIXTURE REFUSED: {error}", file=sys.stderr)
        return 1
    if fixture_controls():
        return 1

    def fixture_cells():
        return (ROOT / "tests/headline_cells.txt").read_text()

    class Controls(unittest.TestCase):
        def setUp(self):
            (ROOT / "build").mkdir(exist_ok=True)
            self.temp = tempfile.TemporaryDirectory(prefix="receipt-self-test-", dir=ROOT / "build")
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name) / "repo"
            self.root.mkdir()
            git(self.root, "init", "-q")
            git(self.root, "config", "user.name", "Receipt self-test")
            git(self.root, "config", "user.email", "receipt-self-test@invalid")
            (self.root / "tests").mkdir()
            (self.root / ".githooks").mkdir()
            (self.root / "build").mkdir()
            (self.root / ".gitignore").write_text("/build/\n/.gate-history/\n__pycache__/\n")
            (self.root / "tests/gate.sh").write_text(f"EXPECT_FULL={expected_count(ROOT, False)}\n")
            (self.root / "tests/headline_cells.txt").write_text(fixture_cells())
            shutil.copyfile(__file__, self.root / "tests/gate_receipt.py")
            shutil.copyfile(ROOT / "tests/abba_evidence.py", self.root / "tests/abba_evidence.py")
            for entry in instrument_fingerprint(ROOT)["entries"]:
                shutil.copyfile(ROOT / entry["path"], self.root / entry["path"])
            from abbagate import read_cells
            from gate_measurements import load as measured_inputs, shape
            config = measured_inputs()
            config["load_floors"] = {}
            config["ceiling_loads"] = {}
            fixture_instrument = instrument_fingerprint(self.root)["sha256"]
            for cell in read_cells(ROOT / "tests/headline_cells.txt"):
                if not saturation_exempt(cell):
                    config["load_floors"][cell.id] = dict(instances=1, shape=shape(cell), status="calibrated",
                        geometry=dict(server_physical=[0, 1], server_smt=[], load_physical=[2, 3],
                                      load_smt=[], split_ratio="1:1"),
                        instrument_sha256=fixture_instrument,
                        observed_rate=dict(unit="ops_per_second", order=["B"], values=[100.]),
                        observed_busy=dict(unit="percent", order=["B"], values=[99.]),
                        provenance=dict(when="synthetic", how="serverless fixture; no measurement"))
            write_json(self.root / "tests/gate_measurements.json", config)
            shutil.copyfile(ROOT / ".githooks/pre-push", self.root / ".githooks/pre-push")
            (self.root / ".githooks/pre-push").chmod(0o755)
            (self.root / "source.cc").write_text("int original;\n")
            (self.root / "alias").symlink_to("source.cc")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-qm", "initial source")
            self.old_oid = git(self.root, "rev-parse", "HEAD").decode().strip()
            # Validate changed, not-yet-committed source and a new source file. The receipt must
            # survive adding/committing their exact bytes later, but cannot approve the old HEAD.
            (self.root / "source.cc").write_text("int candidate;\n")
            (self.root / "new.h").write_text("int new_source;\n")
            self.candidate = self.root / "build/candidate"
            self.candidate.write_bytes(b"synthetic executable bytes, never run\n")
            self.candidate.chmod(0o755)
            self.ledger = self.root / "build/ledger.tsv"
            # Distinct real gate loops can publish the same AOF label. Every occurrence needs
            # its own observation; a set of labels would quietly erase one of these first rows.
            self.ledger.write_text("".join(f"ok\t1.0\t{label}\n" for label in labels))
            self.args = argparse.Namespace(run_id="fixture", tier="push", expected_ledger=self.ledger,
                                           cells=self.root / "tests/headline_cells.txt", nic=False)
            self.start_time = float(int(time.time()) - 40000)
            with mock.patch.object(time, "time", return_value=self.start_time):
                self.start = begin(self.root, self.args)
            with mock.patch.object(time, "time", return_value=self.start_time + 1):
                bind(self.root, argparse.Namespace(start=self.start, candidate=self.candidate))
            self.state = read_json(self.start)
            self.binding = read_json(self.start.parent / "candidate.json")
            self.report = self.make_report(self.start_time + 100, self.binding["sha256"], "b" * 64)
            self.control = self.make_report(self.start_time - 18000, "a" * 64, "a" * 64, is_null=True)
            ended = self.start_time + 16200
            self.completed = dict(schema=1, run_id="fixture", tier="push", completed=True, verdict="PASS",
                                  exit_code=0, started_at=self.start_time, finished_at=ended, checks=expected_count(ROOT, False),
                                  passed=expected_count(ROOT, False), failed=0, skipped=0, abba_exit_code=0, nic_checked=False,
                                  candidate_sha256=self.binding["sha256"])
            self.observed = [dict(schema=1, timing="own-row", run_id="fixture", observation_id=str(i),
                                 label=row["label"], seconds=1., verdict="ok", timed_out=False,
                                 scored=True, ledger_label=row["label"],
                                 recorded_at=self.start_time + 10 + i) for i, row in
                             enumerate(ledger_rows(self.ledger, passing=True))]
            self.finish_args = argparse.Namespace(start=self.start, ledger=self.ledger,
                observations=self.root / "build/observations.jsonl", gate_result=self.root / "build/gate.json",
                abba_result=self.root / "build/abba.json", null_result=self.root / "build/null.json")
            self.save_results()

        def make_report(self, started, candidate, reference, *, is_null=False):
            from _abba_test_fixtures import saturation_record, quiet_record
            rows = []
            for cell in self.state["inventory"]["cells"]:
                runs = [dict(arm=arm, complete=True, artifacts=f"{cell['id']}/n1-{i}-{arm}", pid=100 + i,
                             rate=100., latency_ms=1., p999_ms=2., long_p999_ms=3., commands=2000,
                             midpoint_monotonic=11,
                             window_seconds=20., busy_pct=99., saturation=saturation_record(cell["mode"], threads=2))
                        for i, arm in enumerate(ORDER, 1)]
                rows.append(dict(cell=cell, verdict="PASS", rounds=[dict(instances=1, runs=runs)],
                                 assessment=dict(verdict="PASS", reasons=[], loss_pct=-.1, threshold_pct=.1, instances=1,
                                                 saturation_exempt=saturation_exempt(cell))))
            report = dict(schema=1, verdict="PARTIAL" if is_null else "PASS", subset="full", measurement_valid=True, order=ORDER,
                statistical_verdict="PASS", comparison_trusted=not is_null, run_kind="null-control" if is_null else "comparison", only="",
                started_utc=datetime.fromtimestamp(started, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                elapsed_seconds=16000., window_seconds=20, receipt_harness_sha256=self.state["harness"]["sha256"],
                instrument_fingerprint=copy.deepcopy(self.state["instrument"]),
                cell_source=dict(sha256=self.state["inventory"]["sha256"], total_cells=len(rows),
                                 text=(self.root / "tests/headline_cells.txt").read_text()),
                coverage=dict(ids=[c["id"] for c in self.state["inventory"]["cells"]], count=len(rows), pending_pins=[]),
                candidate=dict(sha256=candidate), reference=dict(sha256=reference),
                environment=dict(port=8700, python_runtime=copy.deepcopy(self.state["instrument"]["python"]),
                                 server_cpus=[0, 1], load_cpus=[2, 3], server_physical=[0, 1],
                                 load_physical=[2, 3], uname=["fixture"], memtier_sha256="d" * 64,
                                 memtier_version="fixture", keys=2000000, data_bytes=64, key_pattern="P:P", split_ratio="1:1",
                                 population_by_arm={"A": "wire", "B": "wire"}),
                quiet_box=quiet_record(cpus=[0, 1, 2, 3], server_physical_cores=2, started_at=started + 1,
                    finished_at=started + 15999, samples=15998),
                cells=rows)
            if is_null:
                report["null_control"] = null_result(report, now=time.time())
            return report

        def save_results(self):
            if "standing_null" not in self.report:
                try:
                    self.report["standing_null"] = match_null(self.report, self.control, now=time.time())
                except ValueError:
                    pass  # Negative fixtures remain malformed until the real validator rejects them.
            write_json(self.finish_args.gate_result, self.completed)
            write_json(self.finish_args.abba_result, self.report)
            write_json(self.finish_args.null_result, self.control)
            self.finish_args.observations.write_text("".join(json.dumps(row) + "\n" for row in self.observed))

        def certify_and_commit(self):
            self.receipt = finish(self.root, self.finish_args)
            with self.assertRaisesRegex(ValueError, "pushed Git tree differs"):
                verify_refs(self.root, [("old", self.old_oid)])
            git(self.root, "add", "source.cc", "new.h")
            git(self.root, "commit", "-qm", "commit exact validated contents")
            self.oid = git(self.root, "rev-parse", "HEAD").decode().strip()
            return self.receipt

        def test_actual_git_refs_hook_and_commit_after_validation(self):
            self.certify_and_commit()
            git(self.root, "update-ref", "refs/heads/certified", self.oid)
            git(self.root, "tag", "-a", "release-fixture", "-m", "same validated tree")
            tag = git(self.root, "rev-parse", "refs/tags/release-fixture").decode().strip()
            self.assertEqual(len(verify_refs(self.root, [("certified", self.oid), ("release-fixture", tag)])), 2)
            stream = f"refs/heads/certified {self.oid} refs/heads/certified {'0' * 40}\n"
            proc = subprocess.run([str(self.root / ".githooks/pre-push"), "fixture", "unused"], cwd=self.root,
                                  input=stream, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("certified by full run fixture", proc.stdout)
            with self.assertRaisesRegex(ValueError, "pushed Git tree differs"):
                verify_refs(self.root, [("old-ref", self.old_oid)])

        def test_missing_rows_cannot_pass_by_count_or_exit_zero(self):
            rows = self.ledger.read_text().splitlines(True)
            self.ledger.write_text("".join(rows[:-1]))
            with self.assertRaisesRegex(ValueError, "missing, duplicated"):
                finish(self.root, self.finish_args)
            self.ledger.write_text("".join(rows))
            self.observed.pop(1)  # The duplicate label is still present; its second execution is not.
            self.save_results()
            with self.assertRaisesRegex(ValueError, "independent own-row"):
                finish(self.root, self.finish_args)

        def test_ledger_and_comparison_guards_have_individual_removal_controls(self):
            original_rows = self.ledger.read_text().splitlines(True)
            original_observed, original_completed = copy.deepcopy(self.observed), copy.deepcopy(self.completed)
            original_report = copy.deepcopy(self.report)
            cases = ("missing real row", "duplicate label", "wrong count", "unowned observation", "bad comparison")
            for case in cases:
                rows = original_rows[:]
                self.observed, self.completed = copy.deepcopy(original_observed), copy.deepcopy(original_completed)
                self.report = copy.deepcopy(original_report)
                message = "missing, duplicated"
                if case == "missing real row":
                    rows.pop(0); self.observed.pop(0)
                elif case == "duplicate label":
                    label = rows[0].rstrip().split("\t")[2]
                    rows[1] = f"ok\t1.0\t{label}\n"
                    self.observed[1].update(label=label, ledger_label=label)
                elif case == "wrong count":
                    self.completed["checks"] -= 1
                    message = "incorrect gate completion checks"
                elif case == "unowned observation":
                    self.observed[0]["timing"] = "borrowed"
                    message = "non-owned timing"
                else:
                    self.report.update(verdict="PARTIAL", comparison_trusted=False)
                    message = "only a complete trusted comparison"
                self.ledger.write_text("".join(rows)); self.save_results()
                with self.assertRaisesRegex(ValueError, message):
                    finish(self.root, self.finish_args)
                saved_require = require
                def removed(condition, reason):
                    if message not in reason:
                        saved_require(condition, reason)
                with mock.patch(__name__ + ".require", new=removed):
                    with self.assertRaises(AssertionError):
                        with self.assertRaisesRegex(ValueError, message):
                            finish(self.root, self.finish_args)
                for name in ("evidence.json", "receipt.json"):
                    (self.start.parent / name).unlink(missing_ok=True)
                print(f"REMOVAL {case}: its exact rejecting assertion failed as required")

        def test_explicit_unscored_dependencies_and_context_do_not_change_counts(self):
            self.observed[0]["label"] += " [external binary: context]"
            self.observed.append(dict(schema=1, timing="own-row", run_id="fixture", observation_id="dependency",
                label="unscored build dependency: core.o", ledger_label=None, scored=False, seconds=2.,
                verdict="ok", timed_out=False, recorded_at=self.start_time + 20))
            self.save_results()
            self.certify_and_commit()
            self.assertEqual(len(verify_refs(self.root, [("HEAD", self.oid)])), 1)

        def test_missing_baseline_retains_start_binding_and_completed_work_without_receipt(self):
            self.args.run_id = "push:bootstrap"
            self.args.expected_ledger = self.root / "build/missing-baseline"
            self.args.allow_missing_baseline = True
            start = begin(self.root, self.args)
            state = read_json(start)
            self.assertIsNone(state["baseline"])
            self.assertIn("missing/invalid trusted baseline", state["withheld_reason"])
            bind(self.root, argparse.Namespace(start=start, candidate=self.candidate))
            args = copy.copy(self.finish_args)
            args.start = start
            with self.assertRaisesRegex(ValueError, "rows are not automatically trusted"):
                finish(self.root, args)
            self.assertFalse((start.parent / "receipt.json").exists())
            self.assertFalse((history_directory(self.root) / "baselines/full.tsv").exists())

        def test_actual_shell_receipt_blocks_do_not_short_circuit_work_or_certify_iteration(self):
            # Execute the gate's real begin/release-binding/footer blocks. Only workload bodies
            # are fake: no make/server/benchmark runs. A missing baseline must still reach both
            # workload markers, bind before them, then exit red with no receipt. Iteration reaches
            # those same markers and invokes no receipt stages even when its counters are green.
            gate = (ROOT / "tests/gate.sh").read_text()
            start_block = gate[gate.index("RECEIPT_REQUIRED=0;"):gate.index('ROW_PLAN="$RUN_DIR/row-timeouts.json"')]
            release = gate[gate.index("job_release(){"):gate.index("\njob_asan(){")]
            final = gate[gate.index("GATE_CLEANUP_RC=$ABBA_CLEANUP_RC\n"): ]
            for tier, built, expected in (("push", 1, 1), ("iteration", 1, 0),
                                           ("push", 0, 1), ("iteration", 0, 0)):
                with self.subTest(tier=tier, built=built):
                    run_id = f"{tier}:fragment-{built}"
                    run = self.root / "build" / ("fragment-" + tier + str(built))
                    run.mkdir()
                    script = '''set -u
RUN_DIR=$TEST_RUN; TMPDIR=$TEST_RUN; ROW_RUN_ID=$TEST_RUN_ID
GATE_STARTED=$SECONDS; GATE_RECEIPT_BASELINE="$PWD/build/missing"
if [ "$TEST_BUILT" = 0 ]; then GATE_RECEIPT_BASELINE="$PWD/build/ledger.tsv"; fi
BUILD_CANDIDATE=$TEST_BUILT; BUILD_CORES=0; BUILD_JOBS=1; CANDIDATE_BINARY="$PWD/build/candidate"
LEDGER="$RUN_DIR/ledger"; TIMINGS="$RUN_DIR/timings"
PASS=0; FAIL=0
row_begin(){ :; }; pausable(){ :; }; ok(){ PASS=$((PASS+1)); }; bad(){ FAIL=$((FAIL+1)); }
cleanup(){ :; }
''' + start_block + release + '''
job_release
if [ "$RECEIPT_REQUIRED" = 1 ]; then
  if [ "$BUILD_CANDIDATE" = 1 ]; then test -f "${RECEIPT_START%/*}/candidate.json" || exit 99
  else test ! -f "${RECEIPT_START%/*}/candidate.json" || exit 98; fi
fi
printf 'correctness\\nabba\\n' > "$RUN_DIR/reached"
PASS=454; FAIL=0; ABBA_RC=0; ABBA_CLEANUP_RC=0; NIC_CHECKED=0; ROW_HISTORY="$PWD/build"
ABBA_OUTPUT="$PWD/build/abba"; LEDGER="$PWD/build/ledger.tsv"
''' + final
                    process = subprocess.run(["bash"], cwd=self.root, input=script, text=True, capture_output=True,
                                             env={**os.environ, "TEST_RUN": str(run), "GATE_PURPOSE": tier,
                                                  "TEST_RUN_ID": run_id, "TEST_BUILT": str(built)})
                    self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
                    self.assertEqual((run / "reached").read_text(), "correctness\nabba\n")
                    self.assertEqual((run / "gate-result.json").exists(), tier == "push")
                    if tier == "push":
                        if built:
                            self.assertIn("rows are not automatically trusted", process.stderr)
                        else:
                            self.assertIn("external bytes cannot certify this source tree", process.stderr)
                    self.assertFalse((history_directory(self.root) / "runs" / run_id / "receipt.json").exists())

        def test_actual_begin_reads_explicit_previous_ledger_before_rotation(self):
            gate = (ROOT / "tests/gate.sh").read_text()
            block = gate[gate.index("LEDGER=${GATE_LEDGER:"):gate.index('ROW_PLAN="$RUN_DIR/row-timeouts.json"')]
            run = self.root / "build" / "explicit-baseline"
            run.mkdir()
            previous = self.ledger.read_bytes()
            script = 'set -u\nRUN_DIR=$TEST_RUN\n' + block + '\nprintf "%s\\n" "$RECEIPT_START"\n'
            process = subprocess.run(["bash"], cwd=self.root, input=script, text=True, capture_output=True,
                env={**os.environ, "TEST_RUN": str(run), "GATE_PURPOSE": "push",
                     "GATE_LEDGER": str(self.ledger), "GATE_RECEIPT_BASELINE": str(self.ledger)})
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            state = read_json(Path(process.stdout.strip()))
            self.assertEqual(state["baseline"]["sha256"], digest(previous))
            self.assertEqual(Counter(state["expected_labels"]), Counter(self.state["expected_labels"]))
            self.assertIsNone(state["withheld_reason"])
            self.assertEqual(self.ledger.read_bytes(), b"")
            self.assertEqual(Path(str(self.ledger) + ".prev").read_bytes(), previous)

        def test_ignored_generated_outputs_preserve_fingerprint_but_tracked_ignored_files_count(self):
            for relative in ("build/obj/source.o", ".gate-history/rows/index.sqlite",
                             "tests/__pycache__/helper.pyc"):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"generated after gate start")
            self.assertEqual(source_fingerprint(self.root), self.state["source"])
            self.certify_and_commit()
            self.assertEqual(len(verify_refs(self.root, [("HEAD", self.oid)])), 1)
            tracked = self.root / "build/forced-tracked-header.h"
            tracked.write_text("tracked despite ignore\n")
            git(self.root, "add", "-f", "build/forced-tracked-header.h")
            fingerprint = source_fingerprint(self.root)
            self.assertTrue(any(row["path"] == "build/forced-tracked-header.h" for row in fingerprint["entries"]))
            tracked.write_text("tracked bytes changed\n")
            self.assertNotEqual(source_fingerprint(self.root), fingerprint)

        def test_actual_history_recorder_matches_context_and_unscored_prerequisites(self):
            import gate_history
            directory = self.root / "build" / "real-history"
            with mock.patch.object(time, "time", return_value=self.start_time + 500):
                for index, row in enumerate(ledger_rows(self.ledger, passing=True)):
                    gate_history.record(directory, run_id=self.args.run_id,
                        label=row["label"] + " [geometry context]", ledger_label=row["label"],
                        seconds=row["seconds"], verdict="ok", timed_out=False, observation_id=f"actual-{index}")
                gate_history.record(directory, run_id=self.args.run_id, label="unscored build dependency: test.o",
                    seconds=2., verdict="ok", timed_out=False, observation_id="actual-dependency", scored=False)
            self.finish_args.observations = directory / gate_history.HISTORY_FILE
            receipt = finish(self.root, self.finish_args)
            retained = read_json(receipt.parent / "evidence.json")["observations"]
            self.assertEqual(sum(row["scored"] for row in retained), expected_count(ROOT, False))
            self.assertEqual(len(retained), expected_count(ROOT, False) + 1)

        def test_future_full_row_count_needs_new_baseline_and_actual_observation(self):
            # Only this disposable Git fixture changes EXPECT. The repository's maintainer-owned
            # constants are never edited; the certificate must follow a future intentional raise.
            (self.root / "tests/gate.sh").write_text(f"EXPECT_FULL={expected_count(ROOT, False) + 1}\n")
            self.args.run_id = "larger-full-run"
            with self.assertRaisesRegex(ValueError, f"exactly {expected_count(ROOT, False) + 1} rows"):
                begin(self.root, self.args)
            self.ledger.write_text(self.ledger.read_text() + "ok\t2.0\tnew required row\n")
            with mock.patch.object(time, "time", return_value=self.start_time):
                self.start = begin(self.root, self.args)
            with mock.patch.object(time, "time", return_value=self.start_time + 1):
                bind(self.root, argparse.Namespace(start=self.start, candidate=self.candidate))
            self.state = read_json(self.start)
            self.binding = read_json(self.start.parent / "candidate.json")
            self.assertEqual(self.state["expected_checks"], expected_count(ROOT, False) + 1)
            self.finish_args.start = self.start
            self.completed["run_id"] = self.args.run_id
            self.report = self.make_report(self.start_time + 100, self.binding["sha256"], "b" * 64)
            self.control = self.make_report(self.start_time - 18000, "a" * 64, "a" * 64, is_null=True)
            for row in self.observed:
                row["run_id"] = self.args.run_id
            self.save_results()
            with self.assertRaisesRegex(ValueError, "incorrect gate completion checks"):
                finish(self.root, self.finish_args)
            self.completed.update(checks=expected_count(ROOT, False) + 1, passed=expected_count(ROOT, False) + 1)
            self.save_results()
            with self.assertRaisesRegex(ValueError, "independent own-row observations"):
                finish(self.root, self.finish_args)
            self.observed.append(dict(schema=1, timing="own-row", run_id=self.args.run_id,
                observation_id="extra", label="new required row", ledger_label="new required row", scored=True,
                seconds=2., verdict="ok", timed_out=False, recorded_at=self.start_time + 100))
            self.save_results()
            self.assertTrue(finish(self.root, self.finish_args).is_file())

        def test_unresolved_cell_names_withhold_receipt_even_with_forged_pass_coordinator(self):
            from _nullrefresh_test import throwaway
            from abbagate import Cell
            row = self.control["cells"][0]
            metric = Cell(**row["cell"]).metric
            row["rounds"][0]["runs"][0][metric] *= 1.1
            self.control["null_control"] = null_result(self.control, now=time.time())
            self.report["standing_null"] = match_null(self.report, self.control, now=time.time())
            self.save_results()
            ident = row["cell"]["id"]
            with self.assertRaisesRegex(ValueError, "receipt withheld: .*UNRESOLVED=1") as caught:
                finish(self.root, self.finish_args)
            self.assertIn(ident, str(caught.exception))
            self.assertFalse((self.start.parent / "receipt.json").exists(), "UNRESOLVED minted a receipt")
            # Remove ONLY the receipt's guard. The deeper comparison guard must
            # still refuse, but the exact receipt-stage refusal oracle is lost.
            with throwaway(sys.modules[__name__], 'finish', 'not summary["unresolved_cells"]', 'True'):
                with self.assertRaises(AssertionError):
                    with self.assertRaisesRegex(ValueError, 'receipt withheld:'):
                        finish(self.root, self.finish_args)
            print(f'UNRESOLVED {ident}: receipt withheld despite PASS coordinator; guard removal changes exact refusal')

        def test_standing_null_replays_saturation_instead_of_cached_pass(self):
            from _abba_test_fixtures import saturation_record
            mutations = (
                lambda run, mode: run.pop("saturation"),
                lambda run, mode: run["saturation"].update(score_pct=100),
                lambda run, mode: run["saturation"]["threads"][0].update(ops_delta=0),
                lambda run, mode: run.update(saturation=saturation_record(mode, score=89, threads=2)),
                lambda run, mode: run.update(saturation=saturation_record(mode, threads=1)),
                lambda run, mode: run.update(saturation=saturation_record(mode, threads=2, window_seconds=19)),
                lambda run, mode: run.update(midpoint_monotonic=31),
                lambda run, mode: run.pop("midpoint_monotonic"),
                lambda run, mode: run.update(
                    saturation=saturation_record(mode, score=98, threads=2, window_seconds=1000),
                    midpoint_monotonic=501),
            )
            for mutate in mutations:
                control = copy.deepcopy(self.control)
                row = next(row for row in control["cells"] if not saturation_exempt(row["cell"]))
                mutate(row["rounds"][0]["runs"][1], row["cell"]["mode"])
                with self.subTest(mutation=mutate), self.assertRaisesRegex(ValueError, "saturation|productive-role"):
                    validate_null(control, now=time.time())

        def test_prior_null_may_have_other_correctness_harness_but_comparison_cannot(self):
            self.control["receipt_harness_sha256"] = "c" * 64
            self.report.pop("standing_null", None)
            self.save_results()
            self.assertTrue(finish(self.root, self.finish_args).is_file())
            self.report["receipt_harness_sha256"] = "c" * 64
            self.report.pop("standing_null", None)
            self.save_results()
            with self.assertRaisesRegex(ValueError, "ABBA harness differs"):
                finish(self.root, self.finish_args)

        def test_selected_core_quiet_evidence_and_diagnostic_poison_controls(self):
            baseline = copy.deepcopy(self.report)
            cases = [
                ("missing quiet policy", lambda: self.report["quiet_box"].pop("policy")),
                ("retired inventory policy", lambda: self.report["quiet_box"].update(policy="operational-environment-v1")),
                ("missing samples", lambda: self.report["quiet_box"].pop("sample_artifact")),
                ("incomplete samples", lambda: self.report["quiet_box"].update(cpu_samples=1)),
                ("unselected CPU included", lambda: self.report["quiet_box"]["cpus"].append(4)),
                ("missing selected CPU", lambda: self.report["quiet_box"]["cpus"].pop()),
                ("no port checks", lambda: self.report["quiet_box"].update(listener_checks=0)),
                ("no intended ports", lambda: self.report["quiet_box"].update(ports=[])),
                ("runtime CPU subtraction claimed", lambda: self.report["quiet_box"]["generic_cpu_screening"].update(scope="continuous")),
                ("budget widened", lambda: self.report["quiet_box"]["generic_cpu_screening"].update(cpu_budget_seconds=1)),
                ("short preflight", lambda: self.report["quiet_box"]["generic_cpu_screening"].update(preflight_seconds=1)),
                ("old diagnostic run", lambda: self.report.update(run_kind="background-qualification")),
                ("ineligible diagnostic run", lambda: self.report.update(normal_gate_eligible=False)),
            ]
            for name, change in cases:
                with self.subTest(name=name):
                    self.report = copy.deepcopy(baseline)
                    change()
                    self.save_results()
                    with self.assertRaises(ValueError):
                        finish(self.root, self.finish_args)

        def test_smoke_partial_failed_unreached_quiet_and_null_controls(self):
            self.args.tier = "smoke"
            with self.assertRaisesRegex(ValueError, "smoke/iteration"):
                begin(self.root, self.args)
            cases = [
                ("smoke", lambda: self.report.update(subset="smoke")),
                ("partial", lambda: self.report.update(verdict="PARTIAL")),
                ("cell failure", lambda: self.report["cells"][0].update(verdict="FAIL")),
                ("missing measurement", lambda: self.report["cells"][0]["rounds"][0]["runs"].pop()),
                ("quiet incomplete", lambda: self.report["quiet_box"].update(complete=False)),
                ("quiet failure", lambda: self.report["quiet_box"].update(interference={"pid": 123})),
                ("null bytes", lambda: self.control["candidate"].update(sha256="c" * 64)),
                ("null instrument", lambda: self.control["instrument_fingerprint"].update(sha256="c" * 64)),
                ("null geometry", lambda: self.control["environment"].update(data_bytes=32)),
                ("null window", lambda: self.control.update(window_seconds=10)),
                ("candidate identity", lambda: self.report["candidate"].update(sha256="c" * 64)),
                ("future null", lambda: self.control.update(started_utc="2999-01-01T00:00:00Z")),
            ]
            baseline_report, baseline_control = copy.deepcopy(self.report), copy.deepcopy(self.control)
            for name, change in cases:
                with self.subTest(name=name):
                    self.report, self.control = copy.deepcopy(baseline_report), copy.deepcopy(baseline_control)
                    change()
                    self.save_results()
                    with self.assertRaises(ValueError):
                        finish(self.root, self.finish_args)
            self.report, self.control = baseline_report, self.make_report(self.start_time - 100000, "a" * 64, "a" * 64, is_null=True)
            self.save_results()
            with self.assertRaisesRegex(ValueError, "24 hours old"):
                finish(self.root, self.finish_args)

        def test_start_end_and_push_source_binary_mode_and_symlink_identity(self):
            source = self.root / "source.cc"
            original = source.read_bytes()
            source.write_bytes(original + b"changed\n")
            with self.assertRaisesRegex(ValueError, "source contents/modes changed"):
                finish(self.root, self.finish_args)
            source.write_bytes(original)
            self.certify_and_commit()
            for kind in ("content", "executable", "new untracked source", "symlink", "binary"):
                with self.subTest(kind=kind):
                    if kind == "content":
                        source.write_bytes(original + b"changed\n")
                    elif kind == "executable":
                        source.chmod(0o755)
                    elif kind == "new untracked source":
                        (self.root / "another.cc").write_text("another source")
                    elif kind == "symlink":
                        (self.root / "alias").unlink()
                        (self.root / "alias").symlink_to("new.h")
                    else:
                        self.candidate.write_bytes(b"another executable")
                    with self.assertRaises(ValueError):
                        verify_refs(self.root, [("HEAD", self.oid)])
                    source.write_bytes(original)
                    source.chmod(0o644)
                    (self.root / "another.cc").unlink(missing_ok=True)
                    (self.root / "alias").unlink()
                    (self.root / "alias").symlink_to("source.cc")

        def test_full_inventory_cannot_retire_a_multikey_geometry(self):
            cells = self.root / "tests/headline_cells.txt"
            rows = cells.read_text().splitlines(True)
            index = next(i for i, row in enumerate(rows) if " | MGET | " in row)
            rows[index] = rows[index].replace("MGET", "GET")
            cells.write_text("".join(rows))
            with self.assertRaisesRegex(ValueError, "retired"):
                inventory(self.root, cells)

        def test_worktree_hook_config_is_reversible_without_common_changes(self):
            # Only temporary repositories are configured; --install is never invoked on ROOT.
            common = self.root / ".git/config"
            prior = common.read_bytes()
            with self.assertRaisesRegex(ValueError, "per-command wrapper"):
                install(self.root)
            self.assertEqual(common.read_bytes(), prior)
            git(self.root, "config", "extensions.worktreeConfig", "true")
            linked = Path(self.temp.name) / "linked"
            git(self.root, "worktree", "add", "--detach", str(linked), "HEAD")
            try:
                prior = common.read_bytes()
                install(linked)
                self.assertEqual(common.read_bytes(), prior)
                self.assertEqual(git(linked, "config", "--worktree", "core.hooksPath").decode().strip(), str(linked / ".githooks"))
                install(linked, uninstall=True)
                self.assertEqual(common.read_bytes(), prior)
            finally:
                git(self.root, "worktree", "remove", "--force", str(linked))

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls))
    from _nullrefresh_test import self_test as promotion_controls
    promoted = promotion_controls()
    refrozen = subprocess.run([sys.executable, str(ROOT / "tests/nullpublish_refreeze_test.py")]).returncode
    return 0 if result.wasSuccessful() and promoted == 0 and refrozen == 0 else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="action")
    frozen = sub.add_parser("freeze-null", help="freeze current runtime inputs after full calibration/import")
    frozen.add_argument("--calibration", type=Path, required=True)
    frozen.add_argument("--output", type=Path, required=True)
    frozen.add_argument("--reorder-controls", type=Path,
                        help="immutable read-local control receipt collected before calibration")
    promotion = sub.add_parser("promote-null", help="explicit local standing-null promotion, never a gate receipt")
    promotion.add_argument("--null-result", type=Path, required=True)
    promotion.add_argument("--campaign", type=Path, required=True)
    sub.add_parser("replay-null", help="historical status table for reporting; never promotion").add_argument("results", type=Path)
    sub.add_parser("resolution-summary", help="name resolving/unresolved cells in a report").add_argument("results", type=Path)
    holdout = sub.add_parser("verify-null-holdout", help="check independent identical arms against frozen errors")
    for name in ("null-result", "comparison", "campaign", "output"):
        holdout.add_argument("--" + name, type=Path, required=True)
    start = sub.add_parser("begin")
    start.add_argument("--run-id", required=True)
    start.add_argument("--tier", choices=("full", "push", "release", "iteration", "smoke"), required=True)
    start.add_argument("--expected-ledger", type=Path, required=True)
    start.add_argument("--cells", type=Path, default=ROOT / "tests/headline_cells.txt")
    start.add_argument("--nic", action="store_true")
    start.add_argument("--nic-auto", action="store_true", help="infer optional NIC inventory from the trusted baseline")
    start.add_argument("--allow-missing-baseline", action="store_true",
                       help="record a withheld bootstrap attempt so the entire authorized gate can still run")
    binding = sub.add_parser("bind")
    binding.add_argument("--start", type=Path, required=True)
    binding.add_argument("--candidate", type=Path, required=True)
    final = sub.add_parser("finish")
    for name in ("start", "gate-result", "ledger", "observations", "abba-result", "null-result"):
        final.add_argument("--" + name, type=Path, required=True)
    completed = sub.add_parser("coordinator")
    completed.add_argument("--start", type=Path)
    completed.add_argument("--output", type=Path, required=True)
    completed.add_argument("--run-id", required=True)
    completed.add_argument("--tier", choices=("full", "push", "release"), required=True)
    for name in ("passed", "failed", "abba-rc", "cleanup-rc"):
        completed.add_argument("--" + name, type=int, required=True)
    completed.add_argument("--nic", type=int, choices=(0, 1), required=True)
    sub.add_parser("fingerprint").add_argument("--harness", action="store_true")
    sub.add_parser("verify").add_argument("--ref", action="append", default=[])
    hook = sub.add_parser("pre-push")
    hook.add_argument("remote", nargs="?")
    hook.add_argument("url", nargs="?")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.install or args.uninstall:
        require(not (args.install and args.uninstall), "choose install or uninstall")
        install(ROOT, uninstall=args.uninstall)
    elif args.action in ("begin", "bind", "finish", "coordinator", "freeze-null", "promote-null", "verify-null-holdout"):
        print(globals()[args.action.replace("-", "_")](ROOT, args))
    elif args.action == "fingerprint":
        print(json.dumps(harness_fingerprint(ROOT) if args.harness else source_fingerprint(ROOT), sort_keys=True))
    elif args.action == "replay-null":
        print(json.dumps(replay_null(args.results), indent=2, allow_nan=False))
    elif args.action == "resolution-summary":
        report = read_json(args.results)
        summary = report.get("resolution_summary")
        require(isinstance(summary, dict), "resolution summary unavailable; no PASS evidence")
        print(resolution_text(summary))
    elif args.action in ("pre-push", "verify"):
        if args.action == "verify":
            updates = [(ref, git(ROOT, "rev-parse", "--verify", ref).decode().strip()) for ref in (args.ref or ["HEAD"])]
        else:
            updates = []
            for line in sys.stdin:
                fields = line.split()
                require(len(fields) == 4, "invalid pre-push ref update")
                updates.append((fields[0], fields[1]))
        for ref, run in verify_refs(ROOT, updates):
            print(f"GATE RECEIPT: {ref} certified by full run {run}")
    else:
        parser.error("choose an action")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"GATE RECEIPT REFUSED: {error}", file=sys.stderr)
        raise SystemExit(1)
