#!/usr/bin/env python3
"""Retain grep receipts for version spellings, including compressed evidence."""
import base64
import gzip
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
old = "0.1-cpp"
patterns = [old, "0\\.1-cpp", old.replace(".", "\\x2e"),
            old.replace(".", "\\u002e"), old.replace(".", "%2E"),
            old.replace("-", "&#45;"), old.replace(".", "&#46;"),
            "".join(f"\\x{ord(c):02x}" for c in old),
            "".join(f"\\u{ord(c):04x}" for c in old),
            "".join(f"\\{ord(c):03o}" for c in old),
            "".join(f"%{ord(c):02X}" for c in old),
            old.encode().hex(), base64.b64encode(old.encode()).decode()]
fields = ["redis_version", "tomokv_version", "kRedisCompatVersion", "kTomoVersion",
          '"version"', "'version'"]
(OUT / "search-patterns.json").write_text(json.dumps(dict(old=patterns, fields=fields), indent=2) + "\n")
for label, needles in (("old-version", patterns), ("version-fields", fields)):
    # Compact receipts retain file, line and exact match even when an archived
    # JSON document occupies one enormous physical line.
    command = ["grep", "-nH", "-I", "-F", "-o"]
    for needle in needles:
        command += ["-e", needle]
    matches = []
    for tree in ("tests", "tools", "docs"):
        for path in sorted((ROOT / tree).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.parent == OUT and \
                    path.name in {"old-version-search.txt", "version-fields-search.txt",
                                  "old-version-search.txt.gz", "version-fields-search.txt.gz",
                                  "search-patterns.json"}:
                continue
            relative = str(path.relative_to(ROOT))
            if path.suffix == ".gz":
                result = subprocess.run([*command, "--label=" + relative + " (gunzip)", "-"],
                                        input=gzip.decompress(path.read_bytes()), capture_output=True)
            else:
                result = subprocess.run([*command, relative], cwd=ROOT, capture_output=True)
            assert result.returncode in (0, 1), (relative, result.stderr)
            matches.append(result.stdout)
    (OUT / f"{label}-search.txt").write_bytes(b"".join(matches))
    print(label, sum(part.count(b"\n") for part in matches), "matching lines")
