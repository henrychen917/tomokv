"""Tracked, content-addressed standing nulls; preserve original evidence bytes.

The registry transports evidence, not trust exceptions. Fingerprint, inventory,
age, geometry and raw-evidence checks still run in match_null. Publication can
explicitly retain PENDING HOLDOUT; historical publication cannot certify today.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import gzip
import json
from pathlib import Path
import shutil
import time

from abba_evidence import canonical, digest, require, utc_seconds
from abba_instrument import validate_fingerprint

_ARTIFACTS = ContextVar("standing_null_artifacts", default={})


class PublishedNull(dict):
    """JSON content is unchanged; relocation metadata never enters its digest."""
    def __init__(self, value, artifacts, directory, receipt):
        super().__init__(value)
        self.artifacts = artifacts
        self.directory, self.receipt = directory, receipt


@contextmanager
def artifact_scope(control):
    token = _ARTIFACTS.set({**_ARTIFACTS.get(), **getattr(control, "artifacts", {})})
    try:
        yield
    finally:
        _ARTIFACTS.reset(token)


def bound_bytes(binding):
    archived = _ARTIFACTS.get().get(binding["sha256"])
    raw = archived if archived is not None else Path(binding["path"]).read_bytes()
    require(digest(raw) == binding["sha256"], f"read-local control artifact changed: {binding['path']}")
    return raw


def default_path(root):
    tracked = Path(root) / "tests/standing-null/current.json"
    return tracked if tracked.is_file() else Path(root) / ".gate-history/receipts/baselines/full-null.json"


def read_blob(directory, binding):
    relative = Path(binding["path"])
    require(not relative.is_absolute() and ".." not in relative.parts, "invalid standing-null artifact path")
    stored = (directory / relative).read_bytes()
    require(digest(stored) == binding["compressed_sha256"], "tracked standing-null compressed artifact changed")
    raw = gzip.decompress(stored)
    require(digest(raw) == binding["sha256"], "tracked standing-null artifact digest differs")
    return raw


def read_null(path):
    from gate_receipt import read_json
    path = Path(path)
    value = read_json(path)
    if value.get("kind") != "tracked-standing-null":
        return value
    require(value.get("schema") == 1 and value.get("independent_resolution") in ("PASS", "PENDING HOLDOUT"),
            "invalid standing-null publication receipt")
    raw = read_blob(path.parent, value["null"])
    control = read_json(path, content=raw)
    fingerprint = validate_fingerprint(control["instrument_fingerprint"])
    require(value["instrument_sha256"] == fingerprint and
            read_json(path.parent / value["instrument_path"]) == control["instrument_fingerprint"],
            "standing-null receipt fingerprint differs")
    require(value["inventory"] == {key: control["cell_source"][key] for key in ("sha256", "total_cells")} and
            value["promotion"] == control.get("promotion"), "standing-null receipt inventory/promotion differs")
    require(digest(read_blob(path.parent, value["source"])) == control["promotion"]["source_sha256"] and
            digest(canonical(json.loads(read_blob(path.parent, value["campaign"])))) ==
            control["promotion"]["campaign_sha256"], "standing-null collection/campaign receipt differs")
    artifacts = {}
    for binding in value["artifacts"]:
        artifacts[binding["sha256"]] = read_blob(path.parent, binding)
    return PublishedNull(control, artifacts, path.parent, value)


def retain(control, path):
    """Freeze the matched artifact and its proof closure beside a gate result."""
    from gate_receipt import write_json
    if not isinstance(control, PublishedNull):
        write_json(path, control)
        return
    receipt = control.receipt
    for binding in [receipt[name] for name in ("null", "source", "campaign", "comparison", "holdout_resolution")
                    if name in receipt] + receipt["artifacts"]:
        target = path.parent / binding["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(control.directory / binding["path"], target)
    shutil.copyfile(control.directory / receipt["instrument_path"], path.parent / receipt["instrument_path"])
    write_json(path, receipt)


def proof_bindings(report):
    if report.get("reorder_controls"):
        yield report["reorder_controls"]
    if report.get("kind") == "read-local-reorder-controls":
        yield report["workloads"]
        proofs = report.get("proofs", {}).values()
    else:
        proofs = (run.get("workload_raw", {}).get("read_local_control") for row in report.get("cells", [])
                  for block in row.get("rounds", []) + row.get("null_repeats", []) + row.get("holdout_repeats", [])
                  for run in block["runs"])
    for proof in proofs:
        if proof:
            yield dict(path=proof["artifact"], sha256=proof["artifact_sha256"])


def publish(root, args):
    from gate_receipt import read_json, write_bytes, write_json
    from abba_evidence import validate_null, validate_campaign_evidence, validate_null_integrity, validate_holdout
    raw = args.null_result.read_bytes()
    control = read_json(args.null_result, content=raw)
    require(control.get("promotion", {}).get("kind") == "standing-null-promotion",
            "publish requires an already promoted null; collection/promotion are separate")
    campaign = read_json(args.campaign)
    fp = validate_fingerprint(control["instrument_fingerprint"])
    require(control["instrument_fingerprint"] == campaign["instrument"] and
            control["promotion"]["instrument_sha256"] == fp and
            control["promotion"]["campaign_sha256"] == digest(canonical(campaign)) and
            control["cell_source"]["sha256"] == campaign["inventory"]["sha256"] and
            [row["cell"] for row in control["cells"]] == campaign["inventory"]["cells"],
            "promoted null differs from frozen campaign/fingerprint/inventory")
    historical = bool(args.historical)
    require(not historical or args.independent_resolution == "PENDING HOLDOUT",
            "historical publication must remain PENDING HOLDOUT")
    now = utc_seconds(control["started_utc"]) + control["elapsed_seconds"] + 1 if historical else time.time()
    if not historical:
        from gate_receipt import validate_campaign
        validate_campaign(root, campaign, control, now=now)
    validate_null(control, now=now)
    validate_campaign_evidence(control)
    validate_null_integrity(control)
    original = Path(control["promotion"]["source_path"]).read_bytes()
    require(digest(original) == control["promotion"]["source_sha256"] and
            read_json(Path(control["promotion"]["source_path"]), content=original) ==
            {key: value for key, value in control.items() if key != "promotion"},
            "promoted null differs from original collection bytes")
    resolution = None
    if args.independent_resolution == "PASS":
        require(args.comparison is not None and args.holdout_resolution is not None,
                "PASS publication requires the independent comparison and verifier artifact")
        comparison = read_json(args.comparison)
        resolution = read_json(args.holdout_resolution)
        expected = validate_holdout(comparison, control, now=time.time())
        require(resolution == expected and expected["independent_resolution"] == "PASS",
                "publication lacks a passing independent holdout; keep PENDING HOLDOUT")
    directory = Path(root) / "tests/standing-null"
    directory.mkdir(parents=True, exist_ok=True)
    def blob(content, name=None):
        stored = gzip.compress(content, mtime=0)
        relative = (name or "artifacts/" + digest(content)) + ".json.gz"
        path = directory / relative
        if path.exists():
            require(path.read_bytes() == stored, "immutable standing-null archive differs")
        else:
            write_bytes(path, stored, exclusive=True)
        return dict(path=relative, sha256=digest(content), compressed_sha256=digest(stored))
    artifacts = {}
    pending = list(proof_bindings(control))
    while pending:
        binding = pending.pop()
        if binding["sha256"] in artifacts:
            continue
        content = bound_bytes(binding)
        artifacts[binding["sha256"]] = blob(content)
        document = json.loads(content)
        if isinstance(document, dict):
            pending.extend(proof_bindings(document))
    instrument_path = fp + ".instrument.json"
    path = directory / instrument_path
    if path.exists():
        require(read_json(path) == control["instrument_fingerprint"], "immutable instrument manifest differs")
    else:
        write_json(path, control["instrument_fingerprint"], exclusive=True)
    receipt = dict(schema=1, kind="tracked-standing-null", instrument_sha256=fp,
        instrument_path=instrument_path, inventory={key: control["cell_source"][key] for key in ("sha256", "total_cells")},
        null=blob(raw, fp + "-" + digest(raw)), source=blob(original), campaign=blob(args.campaign.read_bytes()),
        artifacts=[artifacts[key] for key in sorted(artifacts)], promotion=control["promotion"],
        independent_resolution=args.independent_resolution, historical_publication=historical,
        cycles_op_resolution="UNPROVEN", full_gate_receipt=False)
    if resolution is not None:
        receipt["holdout_resolution"] = blob(args.holdout_resolution.read_bytes())
        receipt["comparison"] = blob(args.comparison.read_bytes())
    receipt_path = directory / (fp + "-" + digest(canonical(receipt)) + ".receipt.json")
    if not receipt_path.exists():
        write_json(receipt_path, receipt, exclusive=True)
    write_json(directory / "current.json", receipt)
    require(read_null(directory / "current.json") == control, "publication round trip changed promoted null")
    return receipt_path
