#!/usr/bin/env python3
"""Compare complete INFO RESP frames under fixed external facts; no normalization."""
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
out = root / "build/rlfix3/info-bytes"
out.mkdir(parents=True, exist_ok=True)
sections = ("server", "clients", "memory", "persistence", "stats", "replication",
            "commandstats", "cluster", "keyspace", "writeback", "lb", "flipctl")
requests = [(), ("default",), ("all",), ("everything",), ("unknown",),
            ("SERVER", "clients", "server"), ("default", "commandstats"),
            ("unknown", "all", "everything"), *((section,) for section in sections)]
rows = []
for image, post in (("multi", "build/rlfix3-info-unit"), ("db0", "build/rlfix3-info-db0-unit")):
    for mode in ("1s", "2s"):
        for shards in (16, 256):
            for index, names in enumerate(requests):
                wires = []
                for arm, binary in (("pre", "build/rlfix3/info-pre-" + image), ("post", post)):
                    result = subprocess.run([str(root / binary), "snapshot", mode, str(shards), *names],
                                            capture_output=True, check=True)
                    wires.append(result.stdout)
                    (out / f"{image}-{mode}-{shards}-{index}-{arm}.resp").write_bytes(result.stdout)
                row = dict(image=image, mode=mode, shards=shards, sections=names,
                           equal=wires[0] == wires[1],
                           sha256=[hashlib.sha256(w).hexdigest() for w in wires])
                rows.append(row)
                if not row["equal"]: print("DIFFER", row, flush=True)
result = dict(comparisons=len(rows), equal=sum(row["equal"] for row in rows), rows=rows)
(root / "docs/rlfix3/info-byte-comparison.json").write_text(json.dumps(result, indent=2) + "\n")
print(f"INFO bytes: {result['equal']}/{result['comparisons']} identical; no fields masked", flush=True)
assert result["equal"] == result["comparisons"]
