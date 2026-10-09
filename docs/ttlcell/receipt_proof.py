#!/usr/bin/env python3
"""Serverless, byte-comparable legacy cell receipts; run before and after editing."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import abbagate as abba
from abba_instrument import instrument_fingerprint
from gate_measurements import shape


def capture(destination):
    destination.mkdir(parents=True, exist_ok=False)
    receipts = getattr(abba, "cell_receipt", asdict)
    manifest = {}
    for label, path in (
            ("headline", ROOT / "tests/headline_cells.txt"),
            ("netio", ROOT / "tests/netio_cells.txt"),
            ("generic", Path("/tmp/claude-1000/generic_merit_cells.txt"))):
        cells = abba.read_cells(path)
        payloads = {
            "receipts": [receipts(cell) for cell in cells],
            "fingerprints": [shape(cell) for cell in cells],
            "coverage": {"subset": "full", **abba.coverage(cells)},
        }
        manifest[label] = dict(path=str(path), count=len(cells),
            file_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for kind, payload in payloads.items():
            content = (json.dumps(payload, indent=2) + "\n").encode()
            (destination / f"{label}-{kind}.json").write_bytes(content)
            manifest[label][kind + "_sha256"] = hashlib.sha256(content).hexdigest()
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (destination / "instrument.json").write_text(
        json.dumps(instrument_fingerprint(ROOT), indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    capture(Path(sys.argv[1]))
