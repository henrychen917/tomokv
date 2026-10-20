#!/usr/bin/env python3
"""Run the unchanged TLS battery while recording its INFO snapshots in memory."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import tls

output = Path(sys.argv[1])
snapshots = []
original = tls.parse_stats


def capture(connection):
    result = original(connection)
    snapshots.append({k: v for k, v in result.items() if k.startswith("tls_")})
    return result


tls.parse_stats = capture
sys.argv = ["tests/tls.py", "127.0.0.1", "25801", str(ROOT / "build/ntfix-certs"),
            "no", "--plain-port", "25800", "--full"]
try:
    tls.main()
finally:
    output.write_text(json.dumps(snapshots, indent=2) + "\n")
